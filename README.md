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
- [Lemonade Server](https://github.com/lemonade-sdk/lemonade) installed and running
- Internet connection for first-time model and embedding downloads

## Installation

1. **Create and activate a virtual environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. **Install dependencies:**
```bash
pip3 install -r requirements.txt
```

## Usage

### Starting the Tool

1. **Make sure lemonade-server is running:**
```bash
lemonade-server start
```

2. **Activate the venv and run Ask Ubuntu:**
```bash
source .venv/bin/activate
./ask-ubuntu
```

On first run the tool will:
- Pull the default model via Lemonade if it isn't already downloaded (~2.5GB)
- Download a small embedding model for documentation search (~100MB)
- Index Ubuntu man pages and help documentation (~2-3 minutes)

The model index is cached, so subsequent runs start instantly.

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

To use a different model, pass `--model` on the command line (the model must exist in Lemonade's catalog):

```bash
./ask-ubuntu --model Qwen3-Coder-Next-GGUF
```

To change the default, update `DEFAULT_MODEL_NAME` and `LEMONADE_BASE_URL` in `main.py`:

```python
DEFAULT_MODEL_NAME = "Qwen3-4B-Instruct-2507-GGUF"
LEMONADE_BASE_URL  = "http://localhost:8000/api/v1"
```

## History

Your question history is saved in `~/.ask_ubuntu_history` and will persist across sessions.

## Tips

- The assistant maintains conversation context, so you can ask follow-up questions
- Responses include formatted code blocks with syntax highlighting
- The assistant focuses on practical, actionable Ubuntu-specific advice
- All commands are explained with context and best practices

## Troubleshooting

**Connection Error**: Make sure Lemonade Server is running — `lemonade-server start`

**Model Pull Error**: Check that the model ID exists in Lemonade's catalog (`curl http://localhost:8000/api/v1/models`) and that you have enough disk space.

**Import Error**: Ensure the venv is active and dependencies are installed — `pip3 install -r requirements.txt`

