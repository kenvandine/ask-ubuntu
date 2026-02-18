# 🟠 Ask Ubuntu - Interactive Terminal Assistant

A modern, interactive shell tool for asking questions about Ubuntu Linux. Features a beautiful terminal UI with markdown rendering, syntax highlighting, and streaming responses.

## Features

- 🎨 **Modern Terminal UI** - Rich markdown rendering with syntax highlighting
- 💬 **Interactive Shell** - Conversation history and context awareness
- ⚡ **Streaming Responses** - See answers appear in real-time
- 📝 **Command History** - Navigate through previous questions with ↑/↓
- 🔧 **Multi-line Input** - Press `Esc` then `Enter` for multi-line queries
- 🎯 **Ubuntu-Focused** - Specialized help for Ubuntu system tasks
- 🧠 **System-Aware** - Automatically detects your Ubuntu version, kernel, desktop environment, and available tools
- 📦 **Package Manager Smart** - Knows about apt, snap, and suggests the right tool for the job
- 🔍 **Context-Aware Advice** - Tailors answers to your specific Ubuntu configuration
- 📚 **RAG-Powered** - Searches actual Ubuntu man pages and help documentation to ground answers
- ⚡ **Semantic Search** - Uses embeddings to find the most relevant documentation for your question
- 🎯 **Authoritative** - Answers based on real Ubuntu documentation, not just LLM knowledge

## Prerequisites

- Python 3.8 or higher
- Lemonade Server installed and accessible
- Internet connection for:
  - First-time model download (7B model, ~4.5GB)
  - First-time embedding model download (~100MB)
  - Documentation indexing (first run only, takes ~2-3 minutes)

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Make the command executable:
```bash
chmod +x ask-ubuntu
```

## Usage

### First Run

The first time you run the tool:
1. It will automatically download the Qwen2.5-Coder-7B-Instruct model (~4.5GB) if not already cached
2. It will download a small embedding model for documentation search (~100MB)
3. It will index Ubuntu man pages and help documentation (~2-3 minutes)
4. The index is cached, so subsequent runs are instant!

**Option 1: Let the tool download, then copy to snap cache**

```bash
# 1. Run the tool (downloads to ~/.cache/huggingface/hub/)
./ask-ubuntu

# 2. Follow the on-screen instructions to copy to snap cache
sudo mkdir -p /var/snap/lemonade-server/common/.cache/huggingface/hub
sudo cp -r ~/.cache/huggingface/hub/models--Qwen--Qwen2.5-Coder-7B-Instruct-GGUF \
  /var/snap/lemonade-server/common/.cache/huggingface/hub/
```

**Option 2: Download directly to snap cache (requires huggingface-cli)**

```bash
# Install huggingface-cli if not already installed
pip install huggingface-hub[cli]

# Download directly to snap cache
sudo HF_HOME=/var/snap/lemonade-server/common/.cache/huggingface \
  huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct-GGUF \
  qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

### Starting the Tool

1. **Make sure lemonade-server is running with the model:**
```bash
# Stop any running lemonade-server
sudo lemonade-server stop

# Start with the downloaded model
sudo lemonade-server run Qwen2.5-Coder-7B-Instruct-GGUF
```

2. **Run Ask Ubuntu:**
```bash
./ask-ubuntu
```

The tool will:
- Check if the model is in lemonade-server's cache
- Connect to lemonade-server on `localhost:8000`
- Start the interactive Ask Ubuntu assistant

### Special Commands

- `/help` - Show help message
- `/clear` - Clear the screen
- `/exit` or `/quit` - Exit the assistant
- `Ctrl+C` - Cancel current input (doesn't exit)
- `Ctrl+D` - Exit the assistant
- `Esc` + `Enter` - Insert newline (multi-line input)

### Example Questions

- "How do I install Docker on Ubuntu?"
- "What's the command to check disk space?"
- "How do I set up a firewall with ufw?"
- "How can I find which process is using port 8080?"
- "What's the best way to update all packages?"
- "Should I install VS Code with apt or snap?"
- "How do I check what version of Ubuntu I'm running?"
- "How can I manage snap packages?"

The assistant will automatically:
- Tailor answers to your specific Ubuntu version and available tools
- Search actual man pages and help docs to ground its answers
- Provide authoritative, documentation-backed responses

## How RAG Works

When you ask a question:
1. Your question is embedded using a semantic search model
2. The tool searches indexed Ubuntu man pages and help documentation
3. Top-3 most relevant documents are retrieved
4. These docs are provided to the LLM as authoritative context
5. The LLM answers based on actual Ubuntu documentation!

**Indexed Documentation:**
- ~500 common man pages (apt, snap, systemctl, docker, git, etc.)
- ~200 Ubuntu help files from `/usr/share/help`
- Cached in `~/.cache/ask-ubuntu/`

## Configuration

To use a different model, edit the constants in `main.py`:

```python
MODEL_REPO = "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"  # HuggingFace repo
MODEL_FILE = "qwen2.5-coder-7b-instruct-q4_k_m.gguf" # GGUF file name
MODEL_NAME = "Qwen2.5-Coder-7B-Instruct-GGUF"        # Model name for lemonade-server
base_url="http://localhost:8000/api/v1"              # Lemonade server URL
```

## History

Your question history is saved in `~/.ask_ubuntu_history` and will persist across sessions.

## Tips

- The assistant maintains conversation context, so you can ask follow-up questions
- Responses include formatted code blocks with syntax highlighting
- The assistant focuses on practical, actionable Ubuntu-specific advice
- All commands are explained with context and best practices

## Troubleshooting

**Model Download Error**: Check your internet connection and ensure you have enough disk space (~5GB)

**Connection Error**:
- Make sure Lemonade Server is running: `sudo lemonade-server status`
- Start it with the correct model: `sudo lemonade-server run Qwen2.5-Coder-7B-Instruct-GGUF`

**Import Error**: Install dependencies with `pip install -r requirements.txt`

**Model Not Found in Lemonade**: The model must be in lemonade-server's snap cache at `/var/snap/lemonade-server/common/.cache/huggingface/hub/`. If you downloaded it to your user cache, copy it there using the commands shown above.

