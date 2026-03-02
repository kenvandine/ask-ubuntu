# Ask Ubuntu — Frequently Asked Questions

## Getting started

### How do I start Ask Ubuntu?

**CLI:** Run `./ask-ubuntu` (or `ask-ubuntu` if installed as a snap) in a terminal.

**GUI:** Launch from your app launcher, or run `cd electron && npm start` in a terminal.

Lemonade Server must be running first. Start it with:
```bash
lemonade-server start
```

### What is Lemonade Server?

Lemonade Server is the local AI inference engine that Ask Ubuntu uses to run the language model on your own machine. It must be running on port 8000 before you start Ask Ubuntu. Install it from the Lemonade project on GitHub.

### Does Ask Ubuntu send data to the internet?

No. All AI inference runs locally via Lemonade Server. Your questions and system info never leave your machine. Man pages may be fetched from manpages.ubuntu.com on first use (to build the local cache), but this is read-only and unauthenticated.

### How long does first startup take?

First startup downloads the AI model (~2–5 GB) and builds a documentation index (~2–3 minutes). Subsequent starts load everything from the cache and take a few seconds.

---

## Using Ask Ubuntu

### How do I ask a question?

Just type at the `●` prompt and press Enter. No special syntax is needed.

### Can I paste multi-line text like an error message?

Yes. Press `Esc` then `Enter` to insert a newline at the CLI prompt. Press `Enter` alone to submit. In the GUI, use `Shift+Enter` for newlines.

### How do I start a new conversation?

**CLI:** The conversation resets when you restart `./ask-ubuntu`.

**GUI:** Click the **+** (new chat) button in the top of the left sidebar.

### How do I clear the CLI screen?

Type `/clear` at the prompt.

### How do I quit Ask Ubuntu?

**CLI:** Type `/exit`, `/quit`, or press `Ctrl+D`.

**GUI:** Close the window.

### Can Ask Ubuntu run commands on my computer?

No. Ask Ubuntu reads system state (package lists, service status, live stats) but never executes commands or makes changes to your system. It will tell you what command to run; you run it yourself.

---

## Models

### How does Ask Ubuntu choose which AI model to use?

It detects your hardware automatically:
1. If you have an AMD NPU (Ryzen AI, Strix Point) and the FLM backend is installed, it uses the best downloaded FLM model (Qwen3-8b-FLM, Phi-4-Mini-FLM, or Llama-3.2-3B-FLM).
2. Otherwise it selects a GGUF model based on your hardware tier (high-end AMD, Intel, balanced AMD, or legacy).

### How do I change the AI model?

**CLI:** Type `/model` to open the interactive model picker. Use arrow keys to navigate, type to search, press Enter to select.

**GUI:** Click the **⊙** model icon button at the top of the left sidebar.

### What do the model badges mean?

- **Recommended** — the model Ask Ubuntu thinks is best for your hardware
- **NPU** — designed to run on the AMD NPU using the FLM backend
- **Downloaded** — already on disk; loads immediately
- No badge — will be downloaded when selected (may take a few minutes)

### How do I download a new model?

In the model picker (CLI `/model` or GUI ⊙ button), select any model that isn't yet downloaded. Ask Ubuntu will download it automatically and switch to it.

### Can I pin a specific model?

Yes. Start Ask Ubuntu with `--model <model-id>` on the CLI, or set the `ASK_UBUNTU_MODEL` environment variable for the GUI.

### What is the FLM backend?

FastFlowLM (FLM) is a backend for running quantized language models natively on the AMD NPU (Neural Processing Unit). It is significantly faster and more power-efficient than running on the CPU. The FLM backend is installed separately as part of the Lemonade NPU stack.

### What models are available?

There are ~70 chat models in Lemonade's catalog, including Llama, Qwen, Phi, Mistral, and others in various sizes and formats (FLM for NPU, GGUF for CPU/GPU). Use the model picker to browse them all.

---

## System information

### What system information does Ask Ubuntu collect?

At startup: OS details, CPU model/cores/governor, GPU name and memory, RAM usage, disk mounts, battery, thermal zones, installed snaps and deb packages, running services. See the left sidebar in the GUI for a quick summary.

### Does Ask Ubuntu see my files?

No. Ask Ubuntu reads system metadata (package lists, service status, hardware info) but never reads your personal files, home directory contents, or any file you haven't explicitly pasted into the chat.

### Why does the system info in the sidebar show a thermal warning?

A thermal alert appears if any CPU or GPU thermal zone is reporting 60°C or higher at startup. This is informational — Ask Ubuntu is telling you your machine is warm. Ask it "is my laptop overheating?" for a detailed analysis.

### How do I refresh the system info?

The system info is collected at startup. Restart Ask Ubuntu (or open a new session) to get a fresh snapshot. Live stats (RAM, CPU, GPU during the conversation) are fetched on demand using the `get_system_stats` tool when you ask questions about current resource usage.

---

## Documentation and RAG

### What documentation does Ask Ubuntu search?

It searches a local vector index of ~500 Ubuntu man pages and ~200 Ubuntu help articles from help.ubuntu.com, plus the Ask Ubuntu user guide itself. This index is built on first run and cached at `~/.cache/ask-ubuntu/`.

### Why doesn't Ask Ubuntu know about a specific man page?

The index covers the most commonly referenced commands. If a man page is missing, Ask Ubuntu will still try to answer from its training knowledge. You can also ask it to check a specific command: "show me the man page for rsync".

### How do I force a rebuild of the documentation index?

```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

Then restart Ask Ubuntu. The index will rebuild from scratch (2–3 minutes).

### How do I get local man pages instead of fetched ones?

Connect the `system-packages-doc` snap interface (available on Ubuntu 24.04+):
```bash
sudo snap connect ask-ubuntu:system-packages-doc
```

This gives the snap read access to `/usr/share/man/` for fast local lookup.

---

## Troubleshooting

### Ask Ubuntu says "Lemonade Server is not running"

Start Lemonade Server:
```bash
lemonade-server start
```

Then relaunch Ask Ubuntu.

### The GUI is stuck on "Starting backend…"

1. Make sure Lemonade Server is running: `curl http://localhost:8000/api/v1/health`
2. Check the terminal for `[server]` error lines — a Python import error or port conflict will show there.

### A model download failed or got stuck

Open the model picker again and try re-selecting the same model. If it fails repeatedly, check that Lemonade Server has internet access and enough disk space (~5 GB free).

### The CLI model picker arrows don't work in my terminal

Some terminals (notably very old xterm variants) don't pass through escape sequences properly. Try a different terminal (GNOME Terminal, Alacritty, Kitty, or the built-in Ubuntu terminal). The picker requires a modern terminal with ANSI escape code support.

### My snap can't read /var/lib/apt/lists or /var/lib/dpkg

The snap interfaces must be connected:
```bash
sudo snap connect ask-ubuntu:var-lib-apt-lists
sudo snap connect ask-ubuntu:var-lib-dpkg
```

After connecting, restart Ask Ubuntu.

### Ask Ubuntu gives wrong answers about my system

Try asking it to re-check with a live tool: "run get_system_stats and tell me what it shows". Also try starting a new conversation — system info is collected at the start of each session.

### How do I report a bug?

Open an issue on the Ask Ubuntu GitHub repository with:
- Your Ubuntu version (`lsb_release -d`)
- The Ask Ubuntu version or git commit
- The exact question you asked and the response you got
- Any error output from the terminal

---

## Privacy and security

### Is my data private?

Yes. All inference runs locally on your machine via Lemonade Server. Nothing is sent to any remote server except:
- Man pages fetched from manpages.ubuntu.com on first use (unauthenticated, read-only)
- Help pages fetched from help.ubuntu.com on first use (unauthenticated, read-only)

### Can Ask Ubuntu modify my system?

No. It reads system state but never runs commands or writes to your files. It tells you what to run; you decide whether to do it.
